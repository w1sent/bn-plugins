// Minimal source exercising the shapes dotnet-native-aot's recovery
// pipeline targets: a base class (virtual dispatch through System.Object),
// a derived class overriding + adding a method, an interface implementation,
// and frozen string/array literals.
using System;

namespace NativeAotTestcase
{
    public interface IGreeter
    {
        string Greet();
    }

    public class Animal : IGreeter
    {
        public string Name = "Animal";

        public virtual string Greet() => $"I am {Name}";

        public override string ToString() => $"Animal({Name})";
    }

    public class Dog : Animal
    {
        public Dog()
        {
            Name = "Dog";
        }

        public override string Greet() => $"Woof, I am {Name}";

        public int Bark(int times) => times * 2;
    }

    public static class Program
    {
        // Frozen string literal -- recovered by FrozenObjectAnnotator.
        private static readonly string Banner = "hello from native aot";

        // Frozen SZ array literal.
        private static readonly int[] Numbers = { 1, 1, 2, 3, 5, 8, 13 };

        public static int Main(string[] args)
        {
            Console.WriteLine(Banner);

            Animal[] animals = { new Animal(), new Dog() };
            foreach (var animal in animals)
            {
                Console.WriteLine(animal.Greet());
                Console.WriteLine(animal.ToString());
                if (animal is IGreeter greeter)
                {
                    Console.WriteLine(greeter.Greet());
                }
            }

            int sum = 0;
            foreach (var n in Numbers)
            {
                sum += n;
            }
            Console.WriteLine($"sum = {sum}");

            return 0;
        }
    }
}
